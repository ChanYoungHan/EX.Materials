module.exports = {
  /**
   * @param db {import('mongodb').Db}
   * @param client {import('mongodb').MongoClient}
   * @returns {Promise<void>}
   */
  async up(db, client) {
    // owner_id가 없는 모든 문서에 owner_id 필드를 추가하고 기본값 228로 설정
    await db.collection('test_documents').updateMany(
      { owner_id: { $exists: false } },
      { $set: { owner_id: 228 } }
    );
  },

  /**
   * @param db {import('mongodb').Db}
   * @param client {import('mongodb').MongoClient}
   * @returns {Promise<void>}
   */
  async down(db, client) {
    // owner_id 필드를 모든 문서에서 제거
    await db.collection('test_documents').updateMany(
      {},
      { $unset: { owner_id: "" } }
    );
  }
};
